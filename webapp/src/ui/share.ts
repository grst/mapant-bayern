import Control from 'ol/control/Control';
import {t} from '../i18n';
import {controlButton, element} from './dom';
import {showToast} from './toast';

/**
 * Copies the current URL, which already carries the view, layers, language and
 * drawings – so there is nothing to build here.
 */
export function createShareControl(target: HTMLElement): Control {
  const container = element('div', 'ol-control share-control');
  const button = controlButton('share', 'share.title');

  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      showToast(t('share.copied'));
    } catch {
      showToast(t('share.failed'), 4000);
    }
  });

  container.append(button);
  return new Control({element: container, target});
}
